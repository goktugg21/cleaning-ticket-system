"""
Sprint 138 §1 + §2 — catalog lifecycle: what the UI is allowed to OFFER.

The whole sprint theme: the interface offered actions that could never
succeed. The operator hit "Deleted 0 service(s), 1 failed" because the
Services list offered Delete on a service that had contract prices — and
the 400 named prices he believed he had already deleted, since Sprint 137
item 2 established that deleting a price ARCHIVES it and an archived
`CustomerServicePrice` still PROTECTs its `Service`.

The fix is to give the client the two facts it needs to decide what to
offer, and to keep the 400s only as backstops:

  * `Service.has_price_rows` — does ANY contract price row reference this
    service, ACTIVE OR ARCHIVED? True ⇒ permanently undeletable ⇒ the UI
    offers Deactiveren instead of Delete.
  * `ServiceCategory.service_count` / `active_service_count` — a category
    holding any service is permanently undeletable (`Service.category` is
    PROTECT and NOT nullable), so Delete is offered only at zero.

Plus the cascade-archive endpoint (§2a): archiving a category archives
its services in ONE transaction, because `Service.category` is not
nullable and leaving active services inside a retired category would
strand them — live in every picker, invisible in the category UI.
Unarchiving restores the CATEGORY ONLY; reactivating a service is a
separate deliberate act.

Covered here:
  * has_price_rows is True for an archived-only price (the reported bug)
  * has_price_rows costs no extra query per row (no N+1)
  * category service counts, scoped to the actor's visible catalog
  * cascade archive: category + services, one transaction, counted
  * unarchive restores the category alone
  * cascade archive is SUPER_ADMIN-only (categories are GLOBAL)
  * an emptied category really can be deleted (nothing else PROTECTs it)
"""
from __future__ import annotations

from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from companies.models import CompanyUserMembership
from customers.models import Customer
from extra_work.models import (
    CustomerServicePrice,
    ExtraWorkPricingUnitType,
    Service,
    ServiceCategory,
)
from test_utils import TenantFixtureMixin


CATEGORY_LIST_URL = "/api/services/categories/"
CATEGORY_DETAIL_URL = "/api/services/categories/{cat_id}/"
CATEGORY_ARCHIVE_URL = "/api/services/categories/{cat_id}/archive/"
CATEGORY_UNARCHIVE_URL = "/api/services/categories/{cat_id}/unarchive/"
SERVICE_LIST_URL = "/api/services/"
SERVICE_DETAIL_URL = "/api/services/{svc_id}/"


class CatalogLifecycleFixtureMixin(TenantFixtureMixin):
    def setUp(self):
        super().setUp()
        CompanyUserMembership.objects.get_or_create(
            user=self.company_admin, company=self.company
        )
        self.category = ServiceCategory.objects.create(name="Cleaning")
        self.empty_category = ServiceCategory.objects.create(name="Empty")
        self.priced_service = Service.objects.create(
            category=self.category,
            company=self.company,
            name="Window cleaning",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("45.00"),
        )
        self.unpriced_service = Service.objects.create(
            category=self.category,
            company=self.company,
            name="Floor polishing",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("38.00"),
        )
        self.pricing_customer = Customer.objects.create(
            company=self.company,
            name="Priced Customer",
            building=self.building,
        )
        # THE reported case: the operator "deleted" this price, which
        # archived it. It still PROTECTs `priced_service`.
        self.archived_price = CustomerServicePrice.objects.create(
            service=self.priced_service,
            customer=self.pricing_customer,
            unit_price=Decimal("40.00"),
            vat_pct=Decimal("21.00"),
            valid_from="2026-01-01",
            is_active=False,
        )


class ServiceHasPriceRowsTests(CatalogLifecycleFixtureMixin, APITestCase):
    def test_archived_only_price_still_marks_service_referenced(self):
        """The exact bug: only an ARCHIVED price exists, and the UI must
        still not offer Delete."""
        self.authenticate(self.super_admin)
        response = self.client.get(SERVICE_LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        by_id = {row["id"]: row for row in response.data["results"]}

        self.assertTrue(by_id[self.priced_service.id]["has_price_rows"])
        self.assertFalse(by_id[self.unpriced_service.id]["has_price_rows"])

    def test_referenced_service_delete_is_still_refused_with_new_wording(
        self,
    ):
        """Backstop: the UI no longer offers this, but a direct API call
        must still be refused — and must not send the operator back
        round the loop of deleting prices that only archive."""
        self.authenticate(self.super_admin)
        response = self.client.delete(
            SERVICE_DETAIL_URL.format(svc_id=self.priced_service.id)
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "service_protected")
        detail = response.data["detail"].lower()
        self.assertIn("archived", detail)
        self.assertIn("deactivate", detail)

    def test_unreferenced_service_delete_still_works(self):
        self.authenticate(self.super_admin)
        response = self.client.delete(
            SERVICE_DETAIL_URL.format(svc_id=self.unpriced_service.id)
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(
            Service.objects.filter(pk=self.unpriced_service.pk).exists()
        )

    def test_has_price_rows_does_not_scale_with_row_count(self):
        """No N+1: the flag comes from ONE EXISTS subquery, so listing
        three services costs the same number of queries as listing one."""
        self.authenticate(self.super_admin)
        with self.assertNumQueries(self._list_query_count()) as _ctx:
            self.client.get(SERVICE_LIST_URL)

        Service.objects.create(
            category=self.category,
            company=self.company,
            name="Extra service A",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("10.00"),
        )
        Service.objects.create(
            category=self.category,
            company=self.company,
            name="Extra service B",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("11.00"),
        )
        # Same query count with 2 more rows — that is the whole claim.
        with self.assertNumQueries(self._list_query_count()):
            self.client.get(SERVICE_LIST_URL)

    def _list_query_count(self):
        """Measure the baseline once so the assertion is about GROWTH,
        not about a brittle absolute number that any unrelated
        middleware change would break."""
        if not hasattr(self, "_cached_list_query_count"):
            from django.test.utils import CaptureQueriesContext
            from django.db import connection

            with CaptureQueriesContext(connection) as ctx:
                self.client.get(SERVICE_LIST_URL)
            self._cached_list_query_count = len(ctx.captured_queries)
        return self._cached_list_query_count


class CategoryServiceCountTests(CatalogLifecycleFixtureMixin, APITestCase):
    def test_counts_reported_per_category(self):
        self.authenticate(self.super_admin)
        response = self.client.get(CATEGORY_LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        by_id = {row["id"]: row for row in response.data["results"]}

        self.assertEqual(by_id[self.category.id]["service_count"], 2)
        self.assertEqual(
            by_id[self.category.id]["active_service_count"], 2
        )
        self.assertEqual(by_id[self.empty_category.id]["service_count"], 0)

    def test_archived_service_still_counts_toward_protect(self):
        """`service_count` drives "may I offer Delete?", and PROTECT does
        not care whether the service is active."""
        self.unpriced_service.is_active = False
        self.unpriced_service.save(update_fields=["is_active"])

        self.authenticate(self.super_admin)
        response = self.client.get(CATEGORY_LIST_URL)
        by_id = {row["id"]: row for row in response.data["results"]}
        self.assertEqual(by_id[self.category.id]["service_count"], 2)
        self.assertEqual(
            by_id[self.category.id]["active_service_count"], 1
        )

    def test_counts_are_scoped_to_the_actors_visible_catalog(self):
        """Categories are GLOBAL but services are company-scoped, so an
        unscoped count would tell a COMPANY_ADMIN a category holds rows
        they cannot see."""
        other_category = ServiceCategory.objects.create(name="Foreign only")
        Service.objects.create(
            category=other_category,
            company=self.other_company,
            name="Someone else's service",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("99.00"),
        )

        self.authenticate(self.company_admin)
        response = self.client.get(CATEGORY_LIST_URL)
        by_id = {row["id"]: row for row in response.data["results"]}
        # Visible to the CA as a (global) category, but holding nothing
        # the CA owns.
        self.assertEqual(by_id[other_category.id]["service_count"], 0)

        # SUPER_ADMIN — the only role that may act on a category — sees
        # the COMPLETE count, which is what PROTECT actually depends on.
        self.authenticate(self.super_admin)
        sa_response = self.client.get(CATEGORY_LIST_URL)
        sa_by_id = {row["id"]: row for row in sa_response.data["results"]}
        self.assertEqual(sa_by_id[other_category.id]["service_count"], 1)


class CategoryCascadeArchiveTests(
    CatalogLifecycleFixtureMixin, APITestCase
):
    def test_archive_cascades_to_services(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            CATEGORY_ARCHIVE_URL.format(cat_id=self.category.id)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["deactivated_service_count"], 2)

        self.category.refresh_from_db()
        self.assertFalse(self.category.is_active)
        self.assertEqual(
            Service.objects.filter(
                category=self.category, is_active=True
            ).count(),
            0,
        )

    def test_unarchive_restores_the_category_only(self):
        """Reactivating a service is a separate deliberate act — it
        becomes orderable again and reappears in every picker."""
        self.authenticate(self.super_admin)
        self.client.post(
            CATEGORY_ARCHIVE_URL.format(cat_id=self.category.id)
        )

        response = self.client.post(
            CATEGORY_UNARCHIVE_URL.format(cat_id=self.category.id)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["deactivated_service_count"], 0)
        self.assertEqual(response.data["still_archived_service_count"], 2)

        self.category.refresh_from_db()
        self.assertTrue(self.category.is_active)
        self.assertEqual(
            Service.objects.filter(
                category=self.category, is_active=True
            ).count(),
            0,
        )

    def test_archive_reports_the_companies_it_reached(self):
        """A GLOBAL category can hold services from several providers;
        archiving it reaches all of them. The count is reported so the
        UI can say so rather than let it happen silently."""
        Service.objects.create(
            category=self.category,
            company=self.other_company,
            name="Other provider's service",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("12.00"),
        )
        self.authenticate(self.super_admin)
        response = self.client.post(
            CATEGORY_ARCHIVE_URL.format(cat_id=self.category.id)
        )
        self.assertEqual(response.data["deactivated_service_count"], 3)
        self.assertEqual(response.data["affected_company_count"], 2)

    def test_company_admin_cannot_cascade_archive(self):
        """Categories are global — same SA-only rule as every other
        category write."""
        self.authenticate(self.company_admin)
        response = self.client.post(
            CATEGORY_ARCHIVE_URL.format(cat_id=self.category.id)
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.category.refresh_from_db()
        self.assertTrue(self.category.is_active)
        self.assertTrue(
            Service.objects.filter(
                category=self.category, is_active=True
            ).exists()
        )

    def test_customer_user_cannot_cascade_archive(self):
        self.authenticate(self.customer_user)
        response = self.client.post(
            CATEGORY_ARCHIVE_URL.format(cat_id=self.category.id)
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class EmptiedCategoryIsDeletableTests(
    CatalogLifecycleFixtureMixin, APITestCase
):
    def test_moving_services_out_then_deleting_actually_works(self):
        """§2c end to end: PROTECT is the ONLY thing standing between a
        category and deletion — `Service.category` is the single FK
        pointing at ServiceCategory — so emptying it is sufficient."""
        self.authenticate(self.super_admin)

        for service in (self.priced_service, self.unpriced_service):
            move = self.client.patch(
                SERVICE_DETAIL_URL.format(svc_id=service.id),
                {"category": self.empty_category.id},
                format="json",
            )
            self.assertEqual(move.status_code, status.HTTP_200_OK, move.data)

        response = self.client.delete(
            CATEGORY_DETAIL_URL.format(cat_id=self.category.id)
        )
        self.assertEqual(
            response.status_code, status.HTTP_204_NO_CONTENT, response.data
        )
        self.assertFalse(
            ServiceCategory.objects.filter(pk=self.category.pk).exists()
        )

    def test_archived_empty_category_is_deletable_too(self):
        """Archived catalog rows are not audit records — an archived
        EMPTY category can still be deleted."""
        self.authenticate(self.super_admin)
        self.empty_category.is_active = False
        self.empty_category.save(update_fields=["is_active"])

        response = self.client.delete(
            CATEGORY_DETAIL_URL.format(cat_id=self.empty_category.id)
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_non_empty_category_delete_is_refused_with_new_wording(self):
        self.authenticate(self.super_admin)
        response = self.client.delete(
            CATEGORY_DETAIL_URL.format(cat_id=self.category.id)
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "category_protected")
        self.assertIn("move", response.data["detail"].lower())


class ServiceCompanyFilterTests(CatalogLifecycleFixtureMixin, APITestCase):
    """Sprint 139 §4 — `?company=` NARROWS the service list. It is
    applied BEFORE `filter_services_for`, so it can never widen what an
    actor sees: a COMPANY_ADMIN naming another company's id gets an
    empty list, not that company's catalog."""

    def setUp(self):
        super().setUp()
        self.foreign_service = Service.objects.create(
            category=self.category,
            company=self.other_company,
            name="Other provider service",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("77.00"),
        )

    def test_super_admin_can_narrow_to_one_company(self):
        self.authenticate(self.super_admin)
        response = self.client.get(
            SERVICE_LIST_URL, {"company": self.other_company.id}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in response.data["results"]}
        self.assertEqual(ids, {self.foreign_service.id})

    def test_company_admin_cannot_widen_via_company_param(self):
        """The load-bearing assertion: asking for a foreign company's id
        returns NOTHING, rather than leaking that company's catalog."""
        self.authenticate(self.company_admin)
        response = self.client.get(
            SERVICE_LIST_URL, {"company": self.other_company.id}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["results"], [])

    def test_company_admin_unfiltered_list_is_still_own_company_only(self):
        self.authenticate(self.company_admin)
        response = self.client.get(SERVICE_LIST_URL)
        companies = {row["company"] for row in response.data["results"]}
        self.assertEqual(companies, {self.company.id})

    def test_garbage_company_param_yields_empty_not_500(self):
        self.authenticate(self.super_admin)
        response = self.client.get(SERVICE_LIST_URL, {"company": "abc"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["results"], [])


class ServiceIsActiveFilterTests(CatalogLifecycleFixtureMixin, APITestCase):
    """Sprint 139 §1 — the Services list hides inactive rows by default
    using the endpoint's EXISTING `?is_active=` param (no second
    mechanism was invented). This locks that the param still works both
    ways, since the frontend default now depends on it."""

    def test_is_active_true_hides_deactivated_services(self):
        self.unpriced_service.is_active = False
        self.unpriced_service.save(update_fields=["is_active"])

        self.authenticate(self.super_admin)
        response = self.client.get(SERVICE_LIST_URL, {"is_active": "true"})
        ids = {row["id"] for row in response.data["results"]}
        self.assertIn(self.priced_service.id, ids)
        self.assertNotIn(self.unpriced_service.id, ids)

    def test_unfiltered_list_still_includes_them(self):
        """The toggle's "show inactive" state sends no param at all, so
        an inactive row must still be reachable — that is how it gets
        reactivated."""
        self.unpriced_service.is_active = False
        self.unpriced_service.save(update_fields=["is_active"])

        self.authenticate(self.super_admin)
        response = self.client.get(SERVICE_LIST_URL)
        ids = {row["id"] for row in response.data["results"]}
        self.assertIn(self.unpriced_service.id, ids)
