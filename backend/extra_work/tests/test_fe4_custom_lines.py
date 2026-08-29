"""
FE-4 (Addendum D §D.12 item 6) — the customer's guided flow submits N
custom "iets anders" lines beside M priced lines through the EXISTING
create endpoint, in exactly the wire shape the frontend builds
(`MeerwerkFlowPage.lineItemsPayload`). This is the frontend-to-API
fixture: the body below IS the body the page posts.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from rest_framework import status as http
from rest_framework.test import APITestCase

from extra_work.models import (
    CustomerServicePrice,
    ExtraWorkPricingUnitType,
    Service,
    ServiceCategory,
)
from test_utils import TenantFixtureMixin


class CustomLinesSubmitTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        category = ServiceCategory.objects.create(company=self.company, name="Cleaning")
        self.service = Service.objects.create(
            category=category,
            company=self.company,
            name="Window cleaning",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
            default_vat_pct=Decimal("21.00"),
        )
        CustomerServicePrice.objects.create(
            service=self.service,
            customer=self.customer,
            unit_price=Decimal("48.50"),
            vat_pct=Decimal("21.00"),
            valid_from=date(2026, 1, 1),
            valid_to=None,
            is_active=True,
        )

    def _frontend_body(self, custom_lines, priced_quantity="2"):
        # Mirrors MeerwerkFlowPage: title / description derived from the
        # cart, one priced line per agreed service, one custom line per
        # "iets anders" entry, each `quantity: "1"`, notes optional.
        line_items = [
            {"service": self.service.id, "quantity": priced_quantity},
        ] + [
            {
                "custom_description": text,
                "quantity": "1",
                **({"customer_note": note} if note else {}),
            }
            for text, note in custom_lines
        ]
        return {
            "building": self.building.id,
            "customer": self.customer.id,
            "title": "Window cleaning +2",
            "description": "\n".join(
                [f"{priced_quantity} × Window cleaning"]
                + [f"Iets anders: {text}" for text, _ in custom_lines]
            ),
            "preferred_date": None,
            "billed_to": None,
            "urgency": "NORMAL",
            "line_items": line_items,
        }

    def test_two_custom_lines_and_one_priced_line_submit(self):
        self.client.force_authenticate(self.customer_user)
        body = self._frontend_body(
            [("Graffiti van de zijgevel", "Bij de fietsenstalling"), ("Kelder ontruimen", "")]
        )
        response = self.client.post("/api/extra-work/", body, format="json")
        self.assertEqual(response.status_code, http.HTTP_201_CREATED, response.data)
        lines = response.data["line_items"]
        self.assertEqual(len(lines), 3)
        custom = [l for l in lines if l["custom_description"]]
        self.assertEqual(
            sorted(l["custom_description"] for l in custom),
            ["Graffiti van de zijgevel", "Kelder ontruimen"],
        )
        self.assertEqual(
            next(l for l in custom if l["custom_description"].startswith("Graffiti"))["customer_note"],
            "Bij de fietsenstalling",
        )
        priced = [l for l in lines if l["service"]]
        self.assertEqual(len(priced), 1)
        # A custom line has no price yet: the request waits for one.
        self.assertEqual(response.data["display_phase"], "WAITING_PRICE")

    def test_three_custom_lines_and_no_priced_line_submit(self):
        self.client.force_authenticate(self.customer_user)
        body = self._frontend_body([("A", ""), ("B", ""), ("C", "")])
        body["line_items"] = body["line_items"][1:]
        response = self.client.post("/api/extra-work/", body, format="json")
        self.assertEqual(response.status_code, http.HTTP_201_CREATED, response.data)
        self.assertEqual(len(response.data["line_items"]), 3)
