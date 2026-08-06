"""
Sprint 137 item 2 — a deleted customer price must not come back unasked.

The reported defect: the operator deletes a price, navigates away, comes
back, and every deleted row is there again, greyed out. DELETE on both
pricing endpoints soft-archives (`is_active=False`), and both list
endpoints returned archived rows unconditionally, so the archived row
reappeared on the next load and the delete looked like it had silently
failed.

Why the rows are still ARCHIVED and not hard-deleted: `ExtraWorkRequestItem
.snapshot_customer_service_price` is a live FK at
`extra_work/models.py:1188` pointing at `CustomerServicePrice` (SET_NULL).
Hard-deleting would null that pointer on already-shipped Extra Work lines
— an irreversible loss of the "which contract row produced this line?"
link. The money itself is safe either way (the `snapshot_*` columns, and
`InvoiceLine` / `ProposalLine`, all carry their own amounts), but there is
no reason to destroy the link when hiding solves the reported bug.

`CustomerCustomPrice` has NO inbound FK at all and could be hard-deleted
by the letter of that rule, but both row types are merged into ONE table
on the pricing page, so "delete" has to mean the same thing on both.

Covered here:
  * default list hides archived rows (both endpoints)
  * `?include_archived=true` brings them back
  * an explicit `?is_active=` still wins, unchanged
  * DELETE still archives rather than destroying the row
"""
from __future__ import annotations

from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from extra_work.models import (
    CustomerCustomPrice,
    CustomerServicePrice,
    ExtraWorkPricingUnitType,
    Service,
    ServiceCategory,
)
from test_utils import TenantFixtureMixin


def pricing_url(customer_id):
    return f"/api/customers/{customer_id}/pricing/"


def pricing_detail_url(customer_id, price_id):
    return f"/api/customers/{customer_id}/pricing/{price_id}/"


def custom_url(customer_id):
    return f"/api/customers/{customer_id}/custom-pricing/"


def custom_detail_url(customer_id, custom_price_id):
    return f"/api/customers/{customer_id}/custom-pricing/{custom_price_id}/"


class ArchivedPricesHiddenByDefaultTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.category = ServiceCategory.objects.create(company=self.company, name="Cleaning")
        self.service = Service.objects.create(
            category=self.category,
            company=self.company,
            name="Window cleaning",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("45.00"),
        )
        self.other_service = Service.objects.create(
            category=self.category,
            company=self.company,
            name="Floor polishing",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("38.00"),
        )
        self.live_price = CustomerServicePrice.objects.create(
            service=self.service,
            customer=self.customer,
            unit_price=Decimal("40.00"),
            vat_pct=Decimal("21.00"),
            valid_from="2026-01-01",
        )
        self.archived_price = CustomerServicePrice.objects.create(
            service=self.other_service,
            customer=self.customer,
            unit_price=Decimal("30.00"),
            vat_pct=Decimal("21.00"),
            valid_from="2026-01-01",
            is_active=False,
        )
        self.live_custom = CustomerCustomPrice.objects.create(
            customer=self.customer,
            custom_name="Graffiti removal",
            unit_type=ExtraWorkPricingUnitType.FIXED,
            unit_price=Decimal("250.00"),
            vat_pct=Decimal("21.00"),
            valid_from="2026-01-01",
        )
        self.archived_custom = CustomerCustomPrice.objects.create(
            customer=self.customer,
            custom_name="Old one-off",
            unit_type=ExtraWorkPricingUnitType.FIXED,
            unit_price=Decimal("99.00"),
            vat_pct=Decimal("21.00"),
            valid_from="2026-01-01",
            is_active=False,
        )
        self.authenticate(self.super_admin)

    def _ids(self, response):
        return {row["id"] for row in response.data["results"]}

    # -- contract prices -------------------------------------------------
    def test_contract_list_hides_archived_by_default(self):
        response = self.client.get(pricing_url(self.customer.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._ids(response), {self.live_price.id})

    def test_contract_list_include_archived_returns_both(self):
        response = self.client.get(
            pricing_url(self.customer.id), {"include_archived": "true"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            self._ids(response),
            {self.live_price.id, self.archived_price.id},
        )

    def test_contract_list_explicit_is_active_false_still_wins(self):
        # The pre-existing `?is_active=` contract is unchanged: it still
        # selects EXACTLY that flag, and is not overridden by the new
        # hide-by-default rule.
        response = self.client.get(
            pricing_url(self.customer.id), {"is_active": "false"}
        )
        self.assertEqual(self._ids(response), {self.archived_price.id})

    def test_malformed_include_archived_fails_safe_to_hidden(self):
        response = self.client.get(
            pricing_url(self.customer.id), {"include_archived": "banana"}
        )
        self.assertEqual(self._ids(response), {self.live_price.id})

    # -- custom prices ---------------------------------------------------
    def test_custom_list_hides_archived_by_default(self):
        response = self.client.get(custom_url(self.customer.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._ids(response), {self.live_custom.id})

    def test_custom_list_include_archived_returns_both(self):
        response = self.client.get(
            custom_url(self.customer.id), {"include_archived": "true"}
        )
        self.assertEqual(
            self._ids(response),
            {self.live_custom.id, self.archived_custom.id},
        )

    # -- the reported round trip ----------------------------------------
    def test_deleted_price_does_not_come_back_on_the_next_load(self):
        """The exact defect: delete, reload, and it is gone from view."""
        delete = self.client.delete(
            pricing_detail_url(self.customer.id, self.live_price.id)
        )
        self.assertEqual(delete.status_code, status.HTTP_204_NO_CONTENT)

        reload = self.client.get(pricing_url(self.customer.id))
        self.assertNotIn(self.live_price.id, self._ids(reload))

        # The row still EXISTS (archived, not destroyed) so the
        # ExtraWorkRequestItem.snapshot_customer_service_price FK that may
        # point at it is never nulled.
        self.live_price.refresh_from_db()
        self.assertFalse(self.live_price.is_active)

        # ...and it is still reachable when explicitly asked for.
        archived = self.client.get(
            pricing_url(self.customer.id), {"include_archived": "true"}
        )
        self.assertIn(self.live_price.id, self._ids(archived))

    def test_deleted_custom_price_does_not_come_back_either(self):
        delete = self.client.delete(
            custom_detail_url(self.customer.id, self.live_custom.id)
        )
        self.assertEqual(delete.status_code, status.HTTP_204_NO_CONTENT)

        reload = self.client.get(custom_url(self.customer.id))
        self.assertNotIn(self.live_custom.id, self._ids(reload))

        self.live_custom.refresh_from_db()
        self.assertFalse(self.live_custom.is_active)
