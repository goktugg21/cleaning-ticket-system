"""P-13 I — actual hours on the LEGACY pricing-items path.

The owner-approved additive migration (0038) gives
`ExtraWorkPricingLineItem` the `actual_hours` triple its cart/proposal
twins have carried since Sprint 8B. This pins the contract:

  * "Save hours to bill" (`POST /actual-hours/`) now lands on a legacy
    hourly line: the hours are stored, `final_*` substitutes them, and
    the QUOTE (`quantity`, the stored line totals, `total_amount`)
    never moves.
  * NULL actual hours = bill the agreed quantity — old behaviour
    unchanged for every legacy row that predates the column.
  * A FIXED legacy line still refuses hours (`actual_hours_not_hourly`).
  * The completion gate (`ew_has_unfinalized_hourly_lines`) now arms on
    a legacy hourly line without hours, exactly like the other paths.
  * Both detail serializers (admin + customer) expose the new field.
"""
from __future__ import annotations

from decimal import Decimal

from extra_work.final_amounts import ew_has_unfinalized_hourly_lines
from extra_work.models import (
    ExtraWorkPricingLineItem,
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
    ExtraWorkStatus,
)
from extra_work.tests.test_m4_billing_run import _InvoiceRunFixture

ACTUAL_HOURS_URL = "/api/extra-work/{id}/actual-hours/"
DETAIL_URL = "/api/extra-work/{id}/"


class LegacyActualHoursTests(_InvoiceRunFixture):
    """An EW priced the old way: no proposal, no INSTANT routing —
    `active_priced_lines` resolves the `pricing_line_items` arm."""

    def _legacy_ew(self):
        ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            # The customer raised it (the realistic legacy shape, and
            # what puts it inside the basic customer user's own-requests
            # scope for the serializer-visibility check below).
            created_by=self.customer_user,
            title="P-13 legacy-priced EW",
            description="d",
            status=ExtraWorkStatus.UNDER_REVIEW,
        )
        hourly = ExtraWorkPricingLineItem.objects.create(
            extra_work=ew,
            description="Deep cleaning",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            quantity=Decimal("6.00"),
            unit_price=Decimal("42.00"),
            vat_rate=Decimal("21.00"),
        )
        fixed = ExtraWorkPricingLineItem.objects.create(
            extra_work=ew,
            description="Materials",
            unit_type=ExtraWorkPricingUnitType.FIXED,
            quantity=Decimal("1.00"),
            unit_price=Decimal("34.00"),
            vat_rate=Decimal("21.00"),
        )
        ew.recompute_totals()
        ew.refresh_from_db()
        return ew, hourly, fixed

    def test_actual_hours_lands_on_a_legacy_hourly_line(self):
        ew, hourly, _fixed = self._legacy_ew()
        # The quote before any hours: 6 x 42 + 34 = 286.00 ex VAT.
        self.assertEqual(ew.subtotal_amount, Decimal("286.00"))
        self.assertIsNone(ew.final_total_amount)

        resp = self._api(self.super_admin).post(
            ACTUAL_HOURS_URL.format(id=ew.id),
            {"lines": [{"line_id": hourly.id, "actual_hours": "6.50"}]},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)

        hourly.refresh_from_db()
        ew.refresh_from_db()
        self.assertEqual(hourly.actual_hours, Decimal("6.50"))
        self.assertEqual(
            hourly.actual_hours_entered_by_id, self.super_admin.id
        )
        self.assertIsNotNone(hourly.actual_hours_entered_at)
        # The QUOTE never moves: ordered quantity, stored line totals,
        # request-level quoted totals all as before.
        self.assertEqual(hourly.quantity, Decimal("6.00"))
        self.assertEqual(hourly.subtotal, Decimal("252.00"))
        self.assertEqual(ew.subtotal_amount, Decimal("286.00"))
        # The FINAL substitutes the hours: 6.5 x 42 + 34 = 307.00.
        self.assertEqual(ew.final_subtotal_amount, Decimal("307.00"))
        self.assertEqual(
            ew.final_total_amount,
            Decimal("307.00") + Decimal("57.33") + Decimal("7.14"),
        )

    def test_null_hours_bill_the_agreed_quantity(self):
        ew, _hourly, _fixed = self._legacy_ew()
        ew.recompute_final_amounts()
        ew.refresh_from_db()
        # No hours entered anywhere: final == quoted, old behaviour.
        self.assertEqual(ew.final_subtotal_amount, ew.subtotal_amount)
        self.assertEqual(ew.final_total_amount, ew.total_amount)

    def test_fixed_legacy_line_refuses_hours(self):
        ew, _hourly, fixed = self._legacy_ew()
        resp = self._api(self.super_admin).post(
            ACTUAL_HOURS_URL.format(id=ew.id),
            {"lines": [{"line_id": fixed.id, "actual_hours": "2.00"}]},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data.get("code"), "actual_hours_not_hourly")

    def test_completion_gate_arms_on_legacy_hourly_lines(self):
        ew, hourly, _fixed = self._legacy_ew()
        self.assertTrue(ew_has_unfinalized_hourly_lines(ew))
        hourly.actual_hours = Decimal("6.50")
        hourly.save(update_fields=["actual_hours", "updated_at"])
        self.assertFalse(ew_has_unfinalized_hourly_lines(ew))

    def test_actual_hours_visible_on_both_detail_serializers(self):
        ew, hourly, _fixed = self._legacy_ew()
        hourly.actual_hours = Decimal("6.50")
        hourly.save(update_fields=["actual_hours", "updated_at"])

        for user in (self.super_admin, self.customer_user):
            resp = self._api(user).get(DETAIL_URL.format(id=ew.id))
            self.assertEqual(resp.status_code, 200, resp.data)
            lines = resp.data["pricing_line_items"]
            by_id = {line["id"]: line for line in lines}
            self.assertEqual(
                by_id[hourly.id]["actual_hours"], "6.50", user.email
            )
